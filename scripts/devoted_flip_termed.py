"""Bucket A: flip 5 stale-termed Devoted policies (real term_date already set, but
status still 'active') to status='termed'. Dry-run default; --apply commits.
SAFETY: only flips a policy that (1) is the exact expected policy id, (2) belongs to
the expected MBI customer, (3) already carries a real term_date. Never bulk.

Run on VPS: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/devoted_flip_termed.py [--apply]
"""
import sys
from app import create_app
from app.extensions import db
from app.models import Policy, Customer

# (policy_id, customer MBI, expected member_id) — the 5 from the read-only diff.
TARGETS = [
    (6082, "1A60NT3JV31", "DJ6ZW7"),   # Vivian Perkins  (term 3/31; switcher->UHC)
    (6081, "1X57MJ7FA64", "DS97W3"),   # Elizabeth Bolder (term 3/31)
    (6083, "4N00NU4TE02", "DRAF2E"),   # Bennie Poole    (term 3/31)
    (12287, "5U63VX3HJ72", "D382J6"),  # Stanley Smith   (term 5/31; switcher->UHC)
    (6087, "6C64U80TF09", "D8H26K"),   # Donna Cook      (term 4/30)
]


def main(apply):
    app = create_app()
    with app.app_context():
        print("%s Bucket A — flip 5 stale-termed Devoted policies\n" % ("APPLY" if apply else "DRY-RUN"))
        flipped = 0
        for pid, mbi, mid in TARGETS:
            p = db.session.get(Policy, pid)
            if p is None:
                print("  ! pol %s missing — SKIP" % pid); continue
            c = db.session.get(Customer, p.customer_id) if p.customer_id else None
            # SAFETY checks
            if p.carrier != "Devoted":
                print("  ! pol %s carrier=%s not Devoted — SKIP" % (pid, p.carrier)); continue
            if not c or (c.mbi or "").upper() != mbi:
                print("  ! pol %s customer mbi=%r != expected %s — SKIP" % (pid, (c.mbi if c else None), mbi)); continue
            if p.member_id != mid:
                print("  ! pol %s member_id=%r != expected %s — SKIP" % (pid, p.member_id, mid)); continue
            if not p.term_date:
                print("  ! pol %s has NO term_date — SKIP (safety: only flip already-termed)" % pid); continue
            if p.status == "termed":
                print("  = pol %s (%s) already termed — no change" % (pid, c.full_name)); continue
            print("  flip pol %s %-20s term=%s  active -> termed" % (pid, c.full_name, p.term_date))
            if apply:
                p.status = "termed"
                flipped += 1
        if apply:
            db.session.commit()
            print("\nAPPLIED — %d flipped." % flipped)
        else:
            db.session.rollback()
            print("\nDRY-RUN — nothing written.")


if __name__ == "__main__":
    main("--apply" in sys.argv)
